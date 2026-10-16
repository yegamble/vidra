import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import peertube_fixture_database as database
import peertube_fixture_media as media


class DatabaseFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'media'
        self.source.mkdir(mode=0o700)
        videos, files = {}, {}
        previous = os.umask(0o077)
        try:
            for name, uuid in media.UUIDS.items():
                original = None if name in ('hls_only', 'split_audio', 'missing_media') else 'web-videos/' + uuid + '.mp4'
                hls = 'streaming-playlists/hls/' + uuid + '/master.m3u8' if name in ('public', 'hls_only', 'split_audio') else None
                videos[name] = dict(uuid=uuid, original=original, hls=hls)
                names = ([original] if original else []) + ([hls, str(Path(hls).parent / 'video.m3u8')] if hls else [])
                if name == 'split_audio':
                    names.append(str(Path(hls).parent / 'audio.m3u8'))
                for relative in names:
                    path = self.source / 'source-media' / relative
                    media.write_private(path, 'unit-only-placeholder')
                    files['source-media/' + relative] = dict(size=path.stat().st_size, sha256=media.sha256(path))
            for relative in ('thumbnails/thumbnail.jpg', 'thumbnails/poster.jpg', 'storyboards/sprite.jpg',
                             'captions/fixture-en.vtt'):
                path = self.source / 'source-media' / relative
                media.write_private(path, 'unit-only-placeholder')
                files['source-media/' + relative] = dict(size=path.stat().st_size, sha256=media.sha256(path))
            self.inventory = dict(format='vidra-peertube-importer-subset-media-v1', core_commit=media.CORE_COMMIT,
                                  intended_schema_marker=1040, unsupported_schema_marker=1041, videos=videos, files=files)
            media.write_private(self.source / 'inventory.json', json.dumps(self.inventory))
        finally:
            os.umask(previous)
        self.identities = {name: {'bcrypt': '$2b$12$' + 'A' * 53} for name in ('alice', 'bob')}
        self.identities['actors'] = {str(number): {'public': 'PUBLIC-CANARY', 'private': "PRIVATE-CANARY'\\\n"}
                                     for number in range(1, 5)}

    def connection(self, tables=None, marker=1040):
        tables = tables if tables is not None else database.graph(self.inventory, self.identities, 'https://source.invalid')
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        # Structural graph check only; SQLite does not certify PostgreSQL/upstream schema.
        connection.executescript(database.render(tables, marker).replace('SET standard_conforming_strings = on;\n', ''))
        return connection

    def test_graph_retains_privacy_moderation_and_actor_relationships(self):
        connection = self.connection()
        query = lambda sql: connection.execute(sql).fetchall()
        self.assertEqual(query('SELECT privacy,state FROM video ORDER BY id'),
                         [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (1, 2), (1, 1), (1, 1), (1, 1), (1, 1)])
        self.assertEqual(query('SELECT username,blocked FROM "user" ORDER BY id'), [('alice', 0), ('bob', 1)])
        self.assertEqual(query('SELECT count(*) FROM actor WHERE ("accountId" IS NOT NULL) != ("videoChannelId" IS NOT NULL)'), [(4,)])
        self.assertEqual(query('SELECT count(*) FROM actor a JOIN account b ON a."accountId"=b.id JOIN "user" u ON b."userId"=u.id'), [(2,)])
        self.assertEqual(query('SELECT count(*) FROM actor a JOIN "videoChannel" c ON a."videoChannelId"=c.id'), [(2,)])
        self.assertEqual(query('SELECT privacy,state FROM video v JOIN "videoBlacklist" b ON b."videoId"=v.id'), [(1, 1)])
        self.assertEqual(query('SELECT count(*) FROM "videoFile" WHERE "videoId"=10'), [(0,)])
        self.assertEqual(query('SELECT count(*) FROM "videoStreamingPlaylist" WHERE "videoId"=10'), [(0,)])
        self.assertEqual(query('SELECT id,"inReplyToCommentId" FROM "videoComment" WHERE "deletedAt" IS NULL ORDER BY id'), [(1, None), (2, 1)])
        self.assertEqual(query('SELECT e."videoId" FROM "videoPlaylistElement" e JOIN "videoPlaylist" p ON p.id=e."videoPlaylistId" WHERE p.type=1 ORDER BY e.position'), [(7,), (1,)])
        self.assertEqual(query('SELECT "actorId","targetActorId" FROM "actorFollow" WHERE state=\'accepted\''), [(3, 2)])
        self.assertEqual(query('SELECT timecode FROM "videoChapter" ORDER BY timecode'), [(0,), (2,)])
        self.assertEqual(query('SELECT count(*) FROM "actorImage"'), [(0,)])

    def test_file_rows_match_existing_measured_media_and_descriptor_semantics(self):
        connection = self.connection()
        self.assertEqual(connection.execute('SELECT count(*) FROM "videoFile" WHERE "videoId" IS NOT NULL').fetchone(), (7,))
        rows = connection.execute('SELECT p."videoId",f.filename,f.resolution,f.size FROM "videoFile" f JOIN "videoStreamingPlaylist" p ON p.id=f."videoStreamingPlaylistId" ORDER BY f.id').fetchall()
        self.assertEqual([(video, name, resolution) for video, name, resolution, _ in rows],
                         [(1, 'video.m3u8', 180), (7, 'video.m3u8', 180), (8, 'video.m3u8', 180), (8, 'audio.m3u8', 0)])
        for video, name, _, size in rows:
            key = 'source-media/streaming-playlists/hls/' + list(media.UUIDS.values())[video - 1] + '/' + name
            self.assertEqual(size, self.inventory['files'][key]['size'])

    def test_refusal_marker_and_escaping_do_not_rewrite_secret_values(self):
        tables = database.graph(self.inventory, self.identities, 'https://source.invalid')
        sql = database.render(tables, 1040)
        refused = database.render(tables, 1041)
        self.assertEqual(sql.replace('VALUES (1, 1040);', 'VALUES (1, 1041);', 1), refused)
        self.assertEqual(self.connection(tables, 1041).execute('SELECT "migrationVersion" FROM application').fetchone(), (1041,))
        self.assertEqual(self.connection(tables).execute('SELECT "privateKey" FROM actor WHERE id=1').fetchone()[0],
                         self.identities['actors']['1']['private'])
        for value in ('bad\0value', object()):
            with self.assertRaises(media.FixtureError):
                database.quote(value)

    def test_input_hash_mode_and_case_tampering_fail_before_output(self):
        self.assertEqual(database.validated_media(self.source), self.inventory)
        path = self.source / next(iter(self.inventory['files']))
        path.write_text('tampered')
        with self.assertRaisesRegex(media.FixtureError, '^media_hash_differs$'):
            database.generate(self.root / 'new', self.source, 'https://source.invalid')
        self.assertFalse((self.root / 'new').exists())
        path.chmod(0o644)
        with self.assertRaisesRegex(media.FixtureError, '^media_permissions_refused$'):
            database.validated_media(self.source)

    def test_origin_and_symlink_refusals_never_print_private_values(self):
        (self.root / 'loop').symlink_to('loop')
        for source, origin in ((self.root / 'loop/new', 'https://source.invalid'),
                               (self.source, 'https://user:PRIVATE-CANARY@source.invalid'),
                               (self.source, 'https://source.invalid/?PRIVATE-CANARY')):
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                self.assertEqual(database.main(['--media', str(source), '--out', str(self.root / 'new'),
                                                '--source-origin', origin]), 1)
            self.assertNotIn('PRIVATE-CANARY', captured.getvalue())
            self.assertNotIn(str(self.root), captured.getvalue())
        self.assertFalse((self.root / 'new').exists())

    def test_generated_state_is_private_input_unchanged_and_stdout_fixed(self):
        before = {path: media.sha256(path) for path in self.source.rglob('*') if path.is_file()}
        def crypto(command, **kwargs):
            output = b'PRIVATE-KEY-CANARY' if 'genpkey' in command else b'PUBLIC-OR-VERSION-CANARY'
            return subprocess.CompletedProcess(command, 0, output, b'PRIVATE-ERROR-CANARY')
        captured = io.StringIO()
        previous = os.umask(0)
        try:
            with patch.object(database, 'bcrypt_hasher', return_value=lambda value: '$2b$12$' + 'A' * 53), \
                    patch.object(database.shutil, 'which', return_value=sys.executable), \
                    patch.object(database.subprocess, 'run', side_effect=crypto), \
                    contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                self.assertEqual(database.main(['--media', str(self.source), '--out', str(self.root / 'new')]), 0)
            self.assertEqual(os.umask(0), 0)
        finally:
            os.umask(previous)
        self.assertEqual(captured.getvalue(), 'peertube_database_fixture_created\n')
        self.assertEqual(before, {path: media.sha256(path) for path in self.source.rglob('*') if path.is_file()})
        for path in [self.root / 'new', *(self.root / 'new').rglob('*')]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
        self.assertIn('PRIVATE-KEY-CANARY', (self.root / 'new/source-1040.sql').read_text())

    def test_existing_output_refuses_before_generating_secrets(self):
        hasher = Mock()
        output = self.root / 'existing'
        output.mkdir(mode=0o700)
        with patch.object(database, 'bcrypt_hasher', return_value=hasher), \
                patch.object(database.shutil, 'which', return_value=sys.executable), \
                patch.object(database.subprocess, 'run') as crypto:
            with self.assertRaisesRegex(media.FixtureError, '^output_exists$'):
                database.generate(output, self.source, 'https://source.invalid')
        hasher.assert_not_called()
        crypto.assert_not_called()

    def test_missing_sql_referenced_asset_refused_even_when_inventory_agrees(self):
        key = 'source-media/thumbnails/poster.jpg'
        (self.source / key).unlink()
        del self.inventory['files'][key]
        (self.source / 'inventory.json').write_text(json.dumps(self.inventory))
        with patch.object(database, 'bcrypt_hasher') as hasher:
            with self.assertRaisesRegex(media.FixtureError, '^sql_media_missing$'):
                database.generate(self.root / 'new', self.source, 'https://source.invalid')
        hasher.assert_not_called()
        self.assertFalse((self.root / 'new').exists())

    def test_output_cannot_mutate_source_tree(self):
        before = {path: media.sha256(path) for path in self.source.rglob('*') if path.is_file()}
        for output in (self.source, self.source / 'new', self.source / 'source-media/new'):
            with patch.object(database, 'bcrypt_hasher') as hasher:
                with self.assertRaisesRegex(media.FixtureError, '^output_overlaps_media$'):
                    database.generate(output, self.source, 'https://source.invalid')
            hasher.assert_not_called()
        self.assertEqual(before, {path: media.sha256(path) for path in self.source.rglob('*') if path.is_file()})

    def test_crypto_failure_never_prints_subprocess_output(self):
        captured = io.StringIO()
        with patch.object(database, 'bcrypt_hasher', return_value=lambda value: '$2b$12$' + 'A' * 53), \
                patch.object(database.shutil, 'which', return_value=sys.executable), \
                patch.object(database.subprocess, 'run', return_value=subprocess.CompletedProcess(
                    [], 1, b'PRIVATE-KEY-CANARY', b'PRIVATE-ERROR-CANARY')), \
                contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            self.assertEqual(database.main(['--media', str(self.source), '--out', str(self.root / 'new')]), 1)
        self.assertEqual(captured.getvalue(), 'actor_key_generation_failed\n')
        self.assertFalse((self.root / 'new/source-1040.sql').exists())

    def test_unexpected_exception_values_remain_redacted(self):
        captured = io.StringIO()
        with patch.object(database, 'generate', side_effect=RuntimeError('PRIVATE-PASSWORD-CANARY')), \
                contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
            self.assertEqual(database.main(['--media', '/PRIVATE-PATH-CANARY', '--out', '/PRIVATE-PATH-CANARY']), 1)
        self.assertEqual(captured.getvalue(), 'fixture_generation_failed\n')


if __name__ == '__main__':
    unittest.main()
