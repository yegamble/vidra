"""Provider readback must prove actual bytes and a complete local HLS graph."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import b2_migration_provider as provider


def sha(body):
    return hashlib.sha256(body).hexdigest()


class ReadOnlyBucket:
    def __init__(self, objects):
        self.objects = objects
        self.gets = []
        self.commands = []

    def inventory(self):
        return [{'fileName': '.vidra/owner', 'action': 'upload', 'contentLength': 1}] + [
            {'fileName': key, 'action': 'upload', 'contentLength': len(body), 'fileId': 'private-version-id'}
            for key, body in self.objects.items()]

    def download_original(self, key, path):
        self.gets.append(key)
        path.write_bytes(self.objects[key])
        # A provider metadata hash is deliberately untrusted. The verifier
        # must hash the downloaded file instead of accepting this assertion.
        return {'status': 200, 'sha256': 'untrusted-metadata-hash'}


class ProviderReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.private = self.root / 'private'
        self.private.mkdir(mode=0o700)
        self.rows, self.objects = [], {}
        self.original = 'web-videos/destination.mp4'
        self.master = 'streaming-playlists/hls/destination/master.m3u8'
        self.variant = 'streaming-playlists/hls/destination/index.m3u8'
        source_master = (b'#EXTM3U\n'
                         b'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub",NAME="English",URI="https://source.invalid/captions/en.vtt"\n'
                         b'#EXT-X-STREAM-INF:BANDWIDTH=1200,CODECS="avc1,mp4a",SUBTITLES="sub"\nvariant.m3u8\n')
        destination_master = (b'#EXTM3U\n'
                              b'#EXT-X-STREAM-INF:BANDWIDTH=1200,CODECS="avc1,mp4a"\nindex.m3u8\n')
        self.add('original', self.original, b'original-video', 'web-videos/original.mp4')
        self.add('playlist', self.master, source_master,
                 'streaming-playlists/hls/source/master.m3u8', destination_master)
        self.add('playlist', self.variant,
                 b'#EXTM3U\n#EXT-X-MAP:URI="init.mp4"\n#EXTINF:1.0,\nsegment.m4s\n#EXT-X-ENDLIST\n',
                 'streaming-playlists/hls/source/variant.m3u8',
                 b'#EXTM3U\n#EXT-X-MAP:URI="media-init.mp4"\n#EXTINF:1.0,\nchunk.m4s\n#EXT-X-ENDLIST\n')
        self.add('hls_binary', 'streaming-playlists/hls/destination/media-init.mp4', b'init-binary',
                 'streaming-playlists/hls/source/init.mp4')
        self.add('hls_binary', 'streaming-playlists/hls/destination/chunk.m4s', b'media-binary',
                 'streaming-playlists/hls/source/segment.m4s')
        self.add('caption', 'captions/destination/import-1.vtt', b'WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n',
                 'captions/en.vtt')
        self.add('artwork', 'thumbnails/destination.jpg', b'poster-binary', 'thumbnails/poster.jpg')
        self.add('storyboard', 'storyboards/destination.jpg', b'sprite-binary', 'storyboards/sprite.jpg')
        self.add('storyboard_vtt', 'storyboards/destination.vtt', b'WEBVTT\n\n', 'expected/storyboard.vtt')

    def add(self, kind, key, source_body, source_key, destination_body=None):
        relative = 'source-media/' + source_key
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source_body)
        row = {'kind': kind, 'key': key, 'source_relative': relative,
               'bytes': len(source_body), 'sha256': sha(source_body)}
        if kind in ('playlist', 'hls_binary'):
            row['source_key'] = source_key
        self.rows.append(row)
        self.objects[key] = source_body if destination_body is None else destination_body

    def pairs(self):
        return provider.validate_pairs(self.rows, self.source)

    def test_every_asset_is_downloaded_and_transformed_playlists_validate_semantics(self):
        bucket = ReadOnlyBucket(self.objects)
        result = provider.verify(bucket, self.pairs(), self.private)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(set(bucket.gets), set(self.objects))
        self.assertEqual(len(bucket.gets), len(self.rows))
        self.assertEqual(result['object_counts']['storyboard_vtt'], 1)
        playlists = [row for row in result['assets'] if row['kind'] == 'playlist']
        self.assertTrue(all(row['playlist_rewrite_valid'] for row in playlists))
        self.assertTrue(all(not row['hash_matches_source'] for row in playlists))
        self.assertTrue(all(row['hash_matches_source'] for row in result['assets']
                            if row['kind'] != 'playlist'))
        published = json.dumps(result)
        for private in ('private-version-id', self.original, self.master, 'source.invalid', str(self.source)):
            self.assertNotIn(private, published)

    def test_same_length_corrupted_binary_cannot_use_metadata_hash_as_attestation(self):
        objects = dict(self.objects, **{self.original: b'corrupted-data'})
        self.assertEqual(len(objects[self.original]), len(self.objects[self.original]))
        with self.assertRaisesRegex(ValueError, 'readback SHA256'):
            provider.verify(ReadOnlyBucket(objects), self.pairs(), self.private)

    def test_playlist_may_not_change_bandwidth_or_point_at_another_local_object(self):
        for body in (self.objects[self.master].replace(b'1200', b'1300'),
                     self.objects[self.master].replace(b'index.m3u8', b'master.m3u8')):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, 'rewrite differs'):
                provider.verify(ReadOnlyBucket(dict(self.objects, **{self.master: body})), self.pairs(), self.private)

    def test_all_uri_positions_reject_remote_traversal_and_encoded_references(self):
        for ref in ('https://remote.invalid/x', '../chunk.m4s', '/chunk.m4s', '%2e%2e/chunk.m4s',
                    'chunk.m4s?token=private', 'chunk.m4s#x', 'nested/chunk.m4s', r'..\chunk.m4s'):
            for template in ('#EXTM3U\n{}\n', '#EXTM3U\n#EXT-X-MAP:URI="{}"\nchunk.m4s\n'):
                with self.subTest(ref=ref, template=template), self.assertRaisesRegex(ValueError, 'nonlocal'):
                    provider.playlist_shape(template.format(ref).encode(), self.variant, set(self.objects))

    def test_destination_may_not_retain_removed_external_subtitles(self):
        body = (self.source / self.rows[1]['source_relative']).read_bytes()
        with self.assertRaisesRegex(ValueError, 'external HLS subtitle'):
            provider.verify(ReadOnlyBucket(dict(self.objects, **{self.master: body})), self.pairs(), self.private)

    def test_missing_extra_hidden_and_duplicate_provider_objects_refused_before_gets(self):
        valid = ReadOnlyBucket(self.objects).inventory()
        inventories = [valid[:-1], valid + [dict(valid[1])],
                       valid + [{'fileName': 'captions/extra.vtt', 'action': 'upload', 'contentLength': 1}],
                       valid + [{'fileName': 'web-videos/../private', 'action': 'upload', 'contentLength': 1}],
                       valid + [{'fileName': self.original, 'action': 'hide', 'contentLength': 1}]]
        for inventory in inventories:
            bucket = ReadOnlyBucket(self.objects)
            with self.subTest(inventory=inventory), patch.object(bucket, 'inventory', return_value=inventory):
                with self.assertRaises(ValueError):
                    provider.verify(bucket, self.pairs(), self.private)
                self.assertFalse(bucket.gets)

    def test_pairs_cannot_omit_an_asset_visible_in_provider_inventory(self):
        rows = [row for row in self.rows if row['kind'] != 'artwork']
        with self.assertRaisesRegex(ValueError, 'absent from asset pairs'):
            provider.verify(ReadOnlyBucket(self.objects), provider.validate_pairs(rows, self.source), self.private)

    def test_sources_must_match_retained_bytes_and_stay_inside_source_root(self):
        rows = copy.deepcopy(self.rows)
        for change in ({'source_relative': '../outside'}, {'key': 'captions/%2e%2e/private.vtt'},
                       {'key': 'other-bucket/secret'}, {'sha256': '0' * 64}, {'bytes': 1}):
            invalid = copy.deepcopy(rows)
            invalid[0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                provider.validate_pairs(invalid, self.source)
        outside = self.root / 'outside'
        outside.write_bytes(b'original-video')
        (self.source / 'escape.mp4').symlink_to(outside)
        rows[0]['source_relative'] = 'escape.mp4'
        with self.assertRaisesRegex(ValueError, 'escapes'):
            provider.validate_pairs(rows, self.source)

    def test_invalid_sources_fail_before_authorization_or_stage_creation(self):
        spec = self.root / 'bucket.json'
        spec.write_text(json.dumps({'bucket': 'vidra-acceptance-v078-20261017-media',
                                    'bucket_id': 'a' * 24, 'region': 'us-east-005',
                                    'endpoint': 's3.us-east-005.backblazeb2.com'}))
        pairs = self.root / 'asset-pairs.json'
        rows = copy.deepcopy(self.rows)
        rows[0]['source_relative'] = '../outside'
        pairs.write_text(json.dumps(rows))
        stage = self.root / 'attempt'
        with patch.object(provider, 'TestBucket') as bucket, self.assertRaises(ValueError):
            provider.execute(pairs, self.source, stage, spec, self.root / 'never-read-key.json', 'v0.7.8')
        bucket.assert_not_called()
        self.assertFalse(stage.exists())

    def test_source_attribute_parser_handles_quoted_commas_and_rejects_ambiguity(self):
        self.assertEqual(provider.attributes('CODECS="avc1,mp4a",BANDWIDTH=1200'),
                         [('CODECS', 'avc1,mp4a', True), ('BANDWIDTH', '1200', False)])
        for value in ('URI="x",URI="y"', 'URI="x"garbage', 'URI="unterminated', 'URI=x,', 'A=one two'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.attributes(value)


if __name__ == '__main__':
    unittest.main()
