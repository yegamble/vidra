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

    def probe_versions(self, key='.vidra/write-probe/ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        return [
            {'fileName': key, 'fileId': 'private-hide-id', 'action': 'hide', 'contentLength': 0,
             'contentType': 'application/x-bz-hide-marker',
             'contentSha1': 'da39a3ee5e6b4b0d3255bfef95601890afd80709', 'uploadTimestamp': 1001},
            {'fileName': key, 'fileId': 'private-upload-id', 'action': 'upload', 'contentLength': 62,
             'contentType': 'application/octet-stream',
             'contentSha1': 'unverified:2e2e018763a941041be9cc97369e15d5ff0781de',
             'uploadTimestamp': 1000}]

    def test_only_completed_frozen_capability_probes_are_separately_accounted_for(self):
        bucket = ReadOnlyBucket(self.objects)
        native = bucket.inventory() + self.probe_versions()
        with patch.object(bucket, 'inventory', return_value=native):
            result = provider.verify(bucket, self.pairs(), self.private)
        self.assertEqual(result['verified_objects'], len(self.rows))
        self.assertEqual(result['provider_version_count'], len(self.rows) + 3)
        self.assertEqual(set(bucket.gets), set(self.objects))
        probes = result['capability_probes']
        self.assertEqual((probes['objects'], probes['provider_versions'], probes['upload_bytes']), (1, 2, 62))
        self.assertEqual(probes['expected_body_sha256'],
                         'a7fe41bf7b24cf3a7472e83a693b1e0b9c6b25f1fc6b7f3f315f371167cb2e07')
        self.assertTrue(probes['frozen_metadata_matches'])
        self.assertFalse(probes['independently_downloaded'])
        self.assertEqual(probes['object_key_sha256'], [sha(self.probe_versions()[0]['fileName'].encode())])
        public = json.dumps(result)
        for private in ('.vidra/write-probe/', 'private-hide-id', 'private-upload-id'):
            self.assertNotIn(private, public)

    def test_probe_key_grammar_is_exact_and_cannot_claim_media_or_an_asset_pair(self):
        for suffix in ('A' * 25, 'A' * 27, 'a' * 26, '0' * 26, '1' * 26, 'A' * 26 + '/media'):
            native = ReadOnlyBucket(self.objects).inventory() + self.probe_versions('.vidra/write-probe/' + suffix)
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'malformed capability'):
                provider.validate_inventory(native, self.pairs())
        native = [row for row in ReadOnlyBucket(self.objects).inventory()
                  if row['fileName'] != self.original] + self.probe_versions(self.original)
        with self.assertRaisesRegex(ValueError, 'hidden/deleted'):
            provider.validate_inventory(native, self.pairs())
        rows = copy.deepcopy(self.rows)
        rows[0]['key'] = self.probe_versions()[0]['fileName']
        with self.assertRaisesRegex(ValueError, 'unsafe relative asset path'):
            provider.validate_pairs(rows, self.source)

    def test_probe_missing_pair_extra_versions_and_nonupload_hide_actions_fail(self):
        versions = self.probe_versions()
        for invalid in (versions[:1], versions[1:], versions + [dict(versions[0])],
                        versions + [dict(versions[1])],
                        [dict(versions[0], action='start'), versions[1]]):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'exactly one upload'):
                provider.validate_inventory(ReadOnlyBucket(self.objects).inventory() + invalid, self.pairs())

    def test_probe_payload_and_hide_metadata_must_match_frozen_write_and_cleanup(self):
        changes = [(1, {'contentLength': 61}), (1, {'contentLength': 63}),
                   (1, {'contentSha1': 'unverified:' + '0' * 40}),
                   (1, {'contentType': 'text/plain'}), (0, {'contentLength': 1}),
                   (0, {'contentSha1': 'none'}), (0, {'contentType': 'application/octet-stream'}),
                   (0, {'uploadTimestamp': 1000}), (0, {'uploadTimestamp': 999}),
                   (0, {'fileId': 'private-upload-id'})]
        for index, change in changes:
            versions = self.probe_versions()
            versions[index].update(change)
            with self.subTest(index=index, change=change), self.assertRaises(ValueError):
                provider.validate_inventory(ReadOnlyBucket(self.objects).inventory() + versions, self.pairs())

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
