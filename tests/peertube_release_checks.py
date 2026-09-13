#!/usr/bin/env python3
"""Supplementary generated-source reconciliation and explicit disconnect controls.

Each action writes a new subdirectory and retains failures. Source-schema writes
address only the disposable clone, never the retained fixture or real PeerTube.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

import release_acceptance as runtime
from blank_server_smoke import require, sha
from peertube_release_acceptance import SOURCE
from release_acceptance_b2 import TestBucket


def original_files(rows):
    # video_files also stores thumbnails and storyboard assets. Reconcile the
    # progressive original population against its own kind, not all file rows.
    originals = [row for row in rows if row['kind'] == 'original']
    require(len(originals) == 5, 'expected five generated progressive originals')
    return originals


def match_assets(source, destination, field):
    expected = {(row['source_id'], row['filename']) for row in source}
    actual = {(row['source_id'], row[field]) for row in destination}
    require(len(expected) == len(source) == len(actual) == len(destination) and actual == expected,
            'media assigned to wrong video, missing, or duplicated')


def execute(stage, action, label=None):
    os.umask(0o077)
    require(re.fullmatch(r'[a-z][a-z0-9-]*', label or action), 'invalid attempt label')
    out = stage / (label or action)
    out.mkdir(mode=0o700)
    run = runtime.Recorder(out)
    result = {'status': 'UNVERIFIED', 'action': action, 'started_at': time.time(), 'checks': {}}
    baseline = Path('/root/vidra-v064-runtime')
    source_media = Path('/root/vidra-v064-migration-20260911/source-media8')
    candidate = json.loads((baseline / 'candidate.json').read_text())
    def source(query):
        return run.run(['docker', 'exec', SOURCE, 'psql', '-U', 'postgres', '-d', 'peertube', '-At',
                        '-v', 'ON_ERROR_STOP=1', '-c', query], 'source-query').strip()
    try:
        result['images_before'] = runtime.runtime_snapshot(run, candidate)
        result['cli_sha256'] = sha(Path('/usr/local/bin/vidra'))
        require(result['cli_sha256'] == candidate['assets']['vidra_v0.6.4_linux_amd64']['sha256'], 'CLI drift')
        result['shipped_files'] = json.loads((baseline / 'frozen-deploy-hashes.json').read_text())
        for name, digest in result['shipped_files'].items():
            require(sha(runtime.INSTALL / name) == digest, 'released tooling drift: ' + name)
        if action in ('restart-before', 'restart-after'):
            require(json.loads((stage / 'disconnect/result.json').read_text())['status'] == 'PASS', 'disconnect first')
            result['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            tables = ('users', 'channels', 'videos', 'comments', 'playlists', 'playlist_items',
                      'channel_follows', 'video_ratings', 'video_tags', 'video_chapters', 'streaming_playlists', 'video_files', 'captions')
            result['catalogue'] = {table: run.sql(f"SELECT count(*)||'|'||md5(COALESCE(string_agg(row::text,E'\\n' ORDER BY row::text),'')) FROM (SELECT to_jsonb(t) AS row FROM {table} t) s") for table in tables}
            result['ledgers'] = {}
            for table, spec in json.loads((baseline / 'expected-ledgers.json').read_text()).items():
                actual = run.sql(f'SELECT version, dirty FROM {table}')
                runtime.check_ledger(actual, spec['version'])
                result['ledgers'][table] = actual
            if action == 'restart-after':
                before = json.loads((stage / 'restart-before/result.json').read_text())
                require(before['status'] == 'PASS' and before['boot_id'] != result['boot_id'], 'host reboot unproved')
                require(before['catalogue'] == result['catalogue'] and before['ledgers'] == result['ledgers'], 'reboot changed persisted catalogue/media state')
                result['checks']['host_restart_state_preserved'] = 'PASS'
        elif action in ('schema-unsupported', 'schema-restore'):
            version = 1040 if action == 'schema-unsupported' else 970
            result['before'] = source('SELECT "migrationVersion" FROM application')
            require(result['before'] == ('970' if version == 1040 else '1040'), 'unexpected clone schema marker')
            source(f'UPDATE application SET "migrationVersion"={version}')
            result['after'] = source('SELECT "migrationVersion" FROM application')
            require(result['after'] == str(version), 'source marker update failed')
            result['checks']['isolated_source_marker'] = 'PASS'
        elif action == 'reconcile':
            result['source_videos'] = json.loads(source('SELECT json_agg(v) FROM (SELECT uuid,name,privacy FROM video ORDER BY uuid) v'))
            result['mapping'] = json.loads(run.sql("SELECT json_agg(v) FROM (SELECT l.source_id,l.vidra_id,l.status,v.title,v.privacy FROM peertube_import_ledger l JOIN videos v ON v.id=l.vidra_id WHERE l.entity_kind='video' ORDER BY l.source_id) v"))
            require(len(result['mapping']) == len(result['source_videos']) == 7, 'video mapping count')
            for src, dst in zip(result['source_videos'], result['mapping']):
                require(str(src['uuid']) == dst['source_id'] and src['name'] == dst['title'] and dst['status'] == 'done', 'source/destination identity mismatch')
                require(dst['privacy'] == {1: 'public', 2: 'unlisted', 3: 'private', 5: 'private'}[src['privacy']], 'privacy mapping differs')
            result['file_metadata'] = json.loads(run.sql("SELECT json_agg(f) FROM (SELECT l.source_id,f.video_id,f.kind,f.storage_key,f.original_name FROM video_files f JOIN peertube_import_ledger l ON f.video_id=l.vidra_id AND l.entity_kind='video') f"))
            keys = original_files(result['file_metadata'])
            originals = json.loads(source('SELECT json_agg(f) FROM (SELECT v.uuid::text AS source_id,f.filename FROM "videoFile" f JOIN video v ON v.id=f."videoId") f'))
            match_assets(originals, keys, 'original_name')
            masters = json.loads(run.sql("SELECT json_agg(p) FROM (SELECT l.source_id,p.video_id,p.master_key FROM streaming_playlists p JOIN peertube_import_ledger l ON p.video_id=l.vidra_id AND l.entity_kind='video') p"))
            require(len(masters) == 6, 'expected six generated HLS playlists')
            source_masters = json.loads(source('SELECT json_agg(p) FROM (SELECT v.uuid::text AS source_id,p."playlistFilename" AS filename FROM "videoStreamingPlaylist" p JOIN video v ON v.id=p."videoId") p'))
            for row in source_masters:
                row['filename'] = 'streaming-playlists/hls/' + row['source_id'] + '/' + row['filename']
            match_assets(source_masters, masters, 'master_key')
            result['source_asset_assignments'] = {'originals': originals, 'hls': source_masters}
            pairs = {}
            for row in keys:
                matches = [p for p in (source_media / 'web-videos').rglob(row['original_name']) if p.is_file()]
                require(len(matches) == 1, 'source progressive filename ambiguous/missing')
                pairs[row['storage_key']] = matches[0]
            def visit(key):
                if key in pairs:
                    return
                require(len(pairs) < 200 and '..' not in Path(key).parts, 'invalid/oversized HLS tree')
                path = source_media / key
                if not path.is_file():
                    path = source_media / key.replace('streaming-playlists/hls/', 'streaming-playlists/hls/private/', 1)
                require(path.is_file(), 'missing source HLS dependency')
                pairs[key] = path
                if key.endswith('.m3u8'):
                    text = path.read_text()
                    require(text.startswith('#EXTM3U'), 'invalid source HLS')
                    refs = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith('#')]
                    refs += re.findall(r'URI="([^"]+)"', text)
                    for ref in refs:
                        require(re.fullmatch(r'[a-zA-Z0-9_-][a-zA-Z0-9_.-]*', ref), 'nonlocal HLS dependency')
                        visit(str(Path(key).parent / ref))
            for master in masters:
                visit(master['master_key'])
            captions = json.loads(run.sql("SELECT json_agg(c) FROM (SELECT l.source_id,c.video_id,c.storage_key,c.language FROM captions c JOIN peertube_import_ledger l ON c.video_id=l.vidra_id AND l.entity_kind='video') c"))
            source_captions = json.loads(source('SELECT json_agg(c) FROM (SELECT v.uuid::text AS source_id,c.filename,c.language FROM "videoCaption" c JOIN video v ON v.id=c."videoId") c'))
            require(len(captions) == len(source_captions) == 1, 'caption count')
            require((captions[0]['source_id'], captions[0]['language']) ==
                    (source_captions[0]['source_id'], source_captions[0]['language']), 'caption assigned to wrong video/language')
            pairs[captions[0]['storage_key']] = source_media / 'captions' / source_captions[0]['filename']
            result['source_asset_assignments']['captions'] = source_captions
            require(len(pairs) == 30, 'expected 30 distinct generated media objects')
            spec = {'bucket': 'vidra-acceptance-v064-20260911-media', 'bucket_id': 'e565124b996984e8a7070215',
                    'region': 'us-east-005', 'endpoint': 's3.us-east-005.backblazeb2.com'}
            bucket = TestBucket(spec, json.loads(Path('/root/vidra-v064-b2-key.json').read_text()))
            result['provider_scope'] = bucket.proof
            result['media'] = []
            for n, (key, path) in enumerate(sorted(pairs.items())):
                downloaded = bucket.download_original(key, run.private / f'media-{n:03d}')
                require(downloaded['sha256'] == sha(path), 'copied media hash mismatch')
                result['media'].append({'key': key, 'source_path': str(path.relative_to(source_media)),
                                        'bytes': downloaded['bytes'], 'sha256': downloaded['sha256'], 'status': downloaded['status']})
            result['provider_commands'] = bucket.commands
            result['checks']['source_ids_privacy_and_media_bytes'] = 'PASS'
            result['search_documents'] = json.loads(run.sql("SELECT json_agg(d) FROM (SELECT l.source_id,d.video_id,d.title,d.eligible FROM search.documents d JOIN peertube_import_ledger l ON d.video_id=l.vidra_id AND l.entity_kind='video' ORDER BY l.source_id) d"))
            eligible = {row['video_id'] for row in result['search_documents'] if row['eligible']}
            expected = {row['vidra_id'] for row in result['mapping'] if row['title'] in
                        ('Migration fixture progressive', 'Migration fixture hls_only', 'Migration fixture split_audio')}
            require(eligible == expected and len(expected) == 3, 'search eligibility differs from fixture')
            # The released importer writes SQL directly, then enqueues a full
            # reconcile.begin/page/end sweep. It does not emit video.upsert.
            result['outbox'] = json.loads(run.sql("SELECT COALESCE(json_agg(e),'[]') FROM (SELECT o.event_id,o.event_type,o.payload->>'run_id' AS run_id,o.created_at,o.state,(i.event_id IS NOT NULL) AS received,ARRAY(SELECT v->>'id' FROM jsonb_array_elements(COALESCE(o.payload->'videos','[]')) v) AS video_ids FROM search_outbox o LEFT JOIN search.events_inbox i USING(event_id) WHERE o.payload->>'run_id' IN (SELECT p.payload->>'run_id' FROM search_outbox p,jsonb_array_elements(COALESCE(p.payload->'videos','[]')) v WHERE p.event_type='reconcile.page' AND v->>'id' IN (SELECT vidra_id::text FROM peertube_import_ledger WHERE entity_kind='video'))) e"))
            require(result['outbox'] and all(row['state'] == 'delivered' and row['received'] for row in result['outbox']), 'import search outbox incomplete')
            require({row['event_type'] for row in result['outbox']} == {'reconcile.begin', 'reconcile.page', 'reconcile.end'}, 'incomplete search sweep')
            require(expected <= {v for row in result['outbox'] for v in row['video_ids']}, 'missing imported public video events')
            search = json.loads(run.run(['docker', 'inspect', run.compose('ps', '-q', 'search').strip()], 'private-search-config'))[0]
            env = dict(value.split('=', 1) for value in search['Config']['Env'] if '=' in value)
            ip = next(n['IPAddress'] for n in search['NetworkSettings']['Networks'].values() if n['IPAddress'])
            path = '/internal/v1/search'
            ts = str(int(time.time()))
            sig = hmac.new(env['INTERNAL_SECRET'].encode(), (ts + '\nGET\n' + path).encode(), hashlib.sha256).hexdigest()
            url = 'http://' + ip + ':8080' + path + '?' + urllib.parse.urlencode({'q': 'Migration fixture', 'limit': 20, 'mode': 'simple', 'personalized': 'false'})
            with urllib.request.urlopen(urllib.request.Request(url, headers={'X-Vidra-Internal-Auth': 'v1:' + ts + ':' + sig}), timeout=20) as response:
                hits = json.load(response)
            result['internal_search_ids'] = [hit['video_id'] for hit in hits['ids']]
            require(set(result['internal_search_ids']) == expected, 'real internal search result differs')
            result['checks']['import_outbox_real_search'] = 'PASS'
        elif action == 'disconnect':
            proofs = [json.loads(p.read_text()) for p in stage.glob('reconcile*/result.json')]
            require(any(p.get('action') == 'reconcile' and p['status'] == 'PASS' and
                        all(p.get('checks', {}).get(k) == 'PASS' for k in ('source_ids_privacy_and_media_bytes', 'import_outbox_real_search'))
                        for p in proofs), 'reconcile before disconnect')
            env_file = runtime.INSTALL / 'env/production.env'
            def unrelated_env():
                return {k: v for k, v in (line.split('=', 1) for line in env_file.read_text().splitlines()
                        if '=' in line and not line.startswith('#')) if not k.startswith('PEERTUBE_')}
            before_env = unrelated_env()
            run.run(['vidra', 'setup', '--template', 'env/production.env.example', '--output', 'env/production.env',
                     '--non-interactive', '--yes', '--no-caddy', '--peertube=false'], 'released-disable-source')
            require(unrelated_env() == before_env, 'setup changed unrelated configuration')
            prod = runtime.INSTALL / 'docker-compose.prod.yml'
            mount = f'  - {source_media}:/peertube-source:ro\n'
            require(prod.read_text().count(mount) == 1, 'unexpected source mount')
            prod.write_text(prod.read_text().replace(mount, ''))
            run.run(['docker', 'stop', SOURCE], 'disconnect-source-database')
            run.run(['bash', 'deploy/deploy.sh'], 'released-deploy-without-source', timeout=1800)
            runtime.wait_for_runtime(run)
            result['checks']['source_disconnected'] = 'PASS'
        result['images_after'] = runtime.runtime_snapshot(run, candidate)
        result['status'] = 'PASS'
    except Exception as error:
        result.update(status='FAIL', error=str(error))
        raise
    finally:
        result['finished_at'] = time.time()
        result['tool_sha256'] = sha(Path(__file__))
        runtime.save(out / 'result.json', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', type=Path)
    parser.add_argument('action', choices=['schema-unsupported', 'schema-restore', 'reconcile', 'disconnect', 'restart-before', 'restart-after'])
    parser.add_argument('--label', help='new attempt name; existing results are never replaced')
    args = parser.parse_args()
    execute(args.stage.resolve(), args.action, args.label)
