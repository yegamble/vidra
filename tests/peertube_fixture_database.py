#!/usr/bin/env python3
"""Create PRIVATE SQL for the frozen importer query subset; never run/import it."""
import argparse
import importlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
import warnings

import peertube_fixture_media as media


SCHEMA = Path(__file__).with_name('peertube_fixture_schema.sql')


def bcrypt_hasher():
    try:
        bcrypt = importlib.import_module('bcrypt')
        return lambda value: bcrypt.hashpw(value.encode(), bcrypt.gensalt(rounds=12)).decode()
    except ImportError:
        # Python <=3.12 on systems with libcrypt's real bcrypt implementation.
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            try:
                crypt = importlib.import_module('crypt')
            except ImportError:
                raise media.FixtureError('bcrypt_dependency_missing') from None
        if not hasattr(crypt, 'METHOD_BLOWFISH') or crypt.METHOD_BLOWFISH not in crypt.methods:
            raise media.FixtureError('bcrypt_dependency_missing')
        return lambda value: crypt.crypt(value, crypt.mksalt(crypt.METHOD_BLOWFISH, rounds=4096))


def validated_media(directory):
    directory = Path(directory)
    try:
        valid = directory.is_absolute() and directory.resolve() == directory and directory.is_dir()
    except (OSError, RuntimeError):
        valid = False
    if not valid or directory.stat().st_mode & 0o077:
        raise media.FixtureError('media_directory_refused')
    for path in directory.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()) or path.stat().st_mode & 0o077:
            raise media.FixtureError('media_permissions_refused')
    inventory = json.loads((directory / 'inventory.json').read_text())
    if (inventory['format'] != 'vidra-peertube-importer-subset-media-v1'
            or inventory['core_commit'] != media.CORE_COMMIT
            or inventory['intended_schema_marker'] != 1040
            or inventory['unsupported_schema_marker'] != 1041
            or inventory['videos'].keys() != media.UUIDS.keys()):
        raise media.FixtureError('media_contract_differs')
    actual = {path.relative_to(directory).as_posix() for path in (directory / 'source-media').rglob('*') if path.is_file()}
    if set(inventory['files']) != actual:
        raise media.FixtureError('media_inventory_differs')
    required = {'source-media/thumbnails/thumbnail.jpg', 'source-media/thumbnails/poster.jpg',
                'source-media/storyboards/sprite.jpg', 'source-media/captions/fixture-en.vtt'}
    if not required <= actual:
        raise media.FixtureError('sql_media_missing')
    for name, record in inventory['files'].items():
        path = directory / name
        if path.stat().st_size != record['size'] or not record['size'] or media.sha256(path) != record['sha256']:
            raise media.FixtureError('media_hash_differs')
    for name, entry in inventory['videos'].items():
        original = None if name in ('hls_only', 'split_audio', 'missing_media') else 'web-videos/' + media.UUIDS[name] + '.mp4'
        hls = ('streaming-playlists/hls/' + media.UUIDS[name] + '/master.m3u8'
               if name in ('public', 'hls_only', 'split_audio') else None)
        if entry != dict(uuid=media.UUIDS[name], original=original, hls=hls):
            raise media.FixtureError('media_contract_differs')
        for kind in ('original', 'hls'):
            if entry[kind] is not None and 'source-media/' + entry[kind] not in actual:
                raise media.FixtureError('media_inventory_differs')
    return inventory


def quote(value):
    if value is None:
        return 'NULL'
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    if not isinstance(value, str) or '\0' in value:
        raise media.FixtureError('sql_value_refused')
    return "'" + value.replace("'", "''") + "'"


def graph(inventory, identities, origin):
    tables = {'actorImage': []}  # Avatar bytes alone do not supply a live HTTP origin.
    def add(table, **row):
        tables.setdefault(table, []).append(row)
    for number, name in enumerate(('alice', 'bob'), 1):
        add('user', id=number, username=name, email=name + '@example.invalid',
            password=identities[name]['bcrypt'], role=2, emailVerified=number == 1, blocked=number == 2)
        add('account', id=number, name=name.title(), userId=number)
        add('videoChannel', id=number, name=name.title() + ' fixture channel', accountId=number,
            description='Synthetic importer query subset', support='Synthetic support copy')
        for actor_id, handle, account, channel in ((number * 2 - 1, name, number, None),
                                                   (number * 2, name + '_channel', None, number)):
            keys = identities['actors'][str(actor_id)]
            add('actor', id=actor_id, type='Person' if account else 'Group', preferredUsername=handle,
                accountId=account, videoChannelId=channel, serverId=None,
                url=origin + ('/accounts/' if account else '/video-channels/') + handle,
                publicKey=keys['public'], privateKey=keys['private'])
    file_id = 0
    for video_id, name in enumerate(media.CASES, 1):
        entry = inventory['videos'][name]
        privacy = {'unlisted': 2, 'private': 3, 'internal': 4, 'password': 5}.get(name, 1)
        add('video', id=video_id, uuid=entry['uuid'], channelId=1,
            name='Synthetic ' + name, description='Importer query subset: ' + name,
            privacy=privacy, state=2 if name == 'draft' else 1, duration=4, views=0, nsfw=False,
            downloadEnabled=name != 'private', commentsPolicy=1, category=1, licence=1, language='en')
        if entry['original']:
            file_id += 1
            record = inventory['files']['source-media/' + entry['original']]
            add('videoFile', id=file_id, videoId=video_id, videoStreamingPlaylistId=None,
                resolution=180, width=320, height=180, fps=25, size=record['size'],
                extname='.mp4', filename=Path(entry['original']).name)
        if entry['hls']:
            add('videoStreamingPlaylist', id=video_id, videoId=video_id, playlistFilename='master.m3u8')
            # Descriptor rows deliberately model queries, not upstream whole-MP4 rows.
            for track in (('video', 'audio') if name == 'split_audio' else ('video',)):
                file_id += 1
                key = 'source-media/' + str(Path(entry['hls']).parent / (track + '.m3u8'))
                add('videoFile', id=file_id, videoId=None, videoStreamingPlaylistId=video_id,
                    resolution=0 if track == 'audio' else 180, width=0 if track == 'audio' else 320,
                    height=0 if track == 'audio' else 180, size=inventory['files'][key]['size'],
                    extname='.m3u8', filename=track + '.m3u8')
    add('thumbnail', id=1, videoId=1, filename='thumbnail.jpg', width=160, height=90)
    add('thumbnail', id=2, videoId=1, filename='poster.jpg', width=320, height=180)
    add('storyboard', id=1, videoId=1, filename='sprite.jpg', totalWidth=320, totalHeight=180,
        spriteWidth=160, spriteHeight=90, spriteDuration=1)
    add('videoCaption', id=1, videoId=1, language='en', filename='fixture-en.vtt')
    add('tag', id=1, name='synthetic')
    add('videoTag', videoId=1, tagId=1)
    add('videoComment', id=1, videoId=1, accountId=1, text='Synthetic root comment')
    add('videoComment', id=2, videoId=1, accountId=2, inReplyToCommentId=1, text='Synthetic reply')
    add('videoComment', id=3, videoId=1, accountId=1, text='Deleted source comment', deletedAt='2026-10-16T00:00:00Z')
    for number, kind in ((1, 1), (2, 2)):
        add('videoPlaylist', id=number, ownerAccountId=1, name='Synthetic playlist ' + str(number), privacy=1, type=kind)
        add('videoPlaylistElement', id=number * 2 - 1, videoPlaylistId=number, videoId=7, position=1)
        add('videoPlaylistElement', id=number * 2, videoPlaylistId=number, videoId=1, position=2)
    add('actorFollow', id=1, actorId=3, targetActorId=2, state='accepted')
    add('actorFollow', id=2, actorId=1, targetActorId=4, state='pending')
    add('videoBlacklist', id=1, videoId=9, reason='Synthetic public quarantine')
    add('videoChapter', id=1, videoId=1, timecode=0, title='Start')
    add('videoChapter', id=2, videoId=1, timecode=2, title='Second half')
    add('accountVideoRate', id=1, videoId=1, accountId=2, type='like')
    return tables


def render(tables, marker):
    if marker not in (1040, 1041):
        raise media.FixtureError('schema_marker_refused')
    lines = ['-- PRIVATE SYNTHETIC IMPORTER QUERY SUBSET; NOT A PEERTUBE EXPORT.',
             'SET standard_conforming_strings = on;', 'BEGIN;', SCHEMA.read_text(),
             f'INSERT INTO application (id, "migrationVersion") VALUES (1, {marker});']
    for table, rows in tables.items():
        for row in rows:
            columns = ','.join('"' + key + '"' for key in row)
            lines.append('INSERT INTO "' + table + '" (' + columns + ') VALUES (' +
                         ','.join(quote(value) for value in row.values()) + ');')
    return '\n'.join([*lines, 'COMMIT;', ''])


def generate(output, source_media, origin):
    parsed = urlsplit(origin)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or (
            parsed.path or parsed.query or parsed.fragment or '\n' in origin or '\r' in origin):
        raise media.FixtureError('source_origin_refused')
    inventory = validated_media(source_media)
    output_path = Path(output).resolve()
    if output_path == Path(source_media) or Path(source_media) in output_path.parents:
        raise media.FixtureError('output_overlaps_media')
    hasher, openssl = bcrypt_hasher(), shutil.which('openssl')
    if not openssl:
        raise media.FixtureError('openssl_dependency_missing')
    previous = os.umask(0o077)
    try:
        root = media.new_private_directory(output)
        credentials = {'actors': {}}
        for name in ('alice', 'bob'):
            password = secrets.token_urlsafe(24)
            hashed = hasher(password)
            if not re.fullmatch(r'\$2[aby]\$12\$[./A-Za-z0-9]{53}', hashed):
                raise media.FixtureError('bcrypt_generation_failed')
            credentials[name] = dict(password=password, bcrypt=hashed)
        def crypto(args, data=None):
            result = subprocess.run([openssl, *args], input=data, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=60)
            if result.returncode:
                raise media.FixtureError('actor_key_generation_failed')
            return result.stdout
        for actor in range(1, 5):
            private = crypto(['genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048'])
            public = crypto(['pkey', '-pubout'], private)
            media.write_private(root / 'keys' / f'actor-{actor}.pem', private)
            credentials['actors'][str(actor)] = dict(private=private.decode(), public=public.decode())
        tables = graph(inventory, credentials, origin)
        for marker in (1040, 1041):
            media.write_private(root / f'source-{marker}.sql', render(tables, marker))
        media.write_private(root / 'credentials.json', json.dumps(credentials, indent=2) + '\n')
        report = dict(format='vidra-peertube-importer-query-subset-v1', qualification='UNVERIFIED',
                      core_commit=media.CORE_COMMIT, supported_schema_contract=[700, 1040],
                      positive_schema_marker=1040, refusal_schema_marker=1041, source_origin=origin,
                      source_media_inventory_sha256=media.sha256(Path(source_media) / 'inventory.json'),
                      table_rows={'application': 1, **{name: len(rows) for name, rows in tables.items()}},
                      crypto_tool=dict(path=str(Path(openssl).resolve()), sha256=media.sha256(openssl),
                                       version=crypto(['version', '-a']).decode(), rsa_bits=2048, bcrypt_cost=12),
                      hls_rows='Synthetic playlist descriptors: size is playlist bytes, not payload/rung bytes.',
                      exclusions=['No actual PeerTube server/version certification or export.',
                                  'No database creation/load/import, roles/grants or upstream constraints.',
                                  'No remote followers, plugin auth, history, ZIP archive or network service.',
                                  'actorImage is empty: avatar import needs a future live source HTTP origin.',
                                  'No representative G10/recovery/browser qualification.'])
        media.write_private(root / 'inventory.json', json.dumps(report, indent=2) + '\n')
    finally:
        os.umask(previous)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--media', required=True)
    parser.add_argument('--source-origin', default='https://synthetic-peertube.invalid')
    args = parser.parse_args(argv)
    try:
        generate(args.out, args.media, args.source_origin)
    except media.FixtureError as error:
        print(str(error), file=sys.stderr)
        return 1
    except Exception:
        print('fixture_generation_failed', file=sys.stderr)
        return 1
    print('peertube_database_fixture_created')
    return 0


if __name__ == '__main__':
    sys.exit(main())
