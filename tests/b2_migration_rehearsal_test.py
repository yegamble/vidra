"""Offline checks for the B2 rehearsal's evidence and credential boundaries."""
import copy
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import b2_migration_rehearsal as rehearsal
import peertube_fixture_media as media


ROOT = Path(__file__).resolve().parents[1]


class PrivateInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.path = self.root / 'credentials.json'
        self.path.write_text('{"access_key":"PRIVATE-CANARY"}')
        self.path.chmod(0o600)

    def test_private_json_can_be_read(self):
        self.assertEqual(rehearsal.read_private_json(self.path),
                         {'access_key': 'PRIVATE-CANARY'})

    def test_group_and_world_permissions_are_refused(self):
        for mode in (0o640, 0o604, 0o644):
            with self.subTest(mode=oct(mode)):
                self.path.chmod(mode)
                with self.assertRaises(rehearsal.Failure):
                    rehearsal.read_private_json(self.path)

    def test_symlink_and_parent_symlink_are_refused(self):
        link = self.root / 'link.json'
        link.symlink_to(self.path)
        directory_link = self.root / 'alias'
        directory_link.symlink_to(self.root, target_is_directory=True)
        for path in (link, directory_link / self.path.name):
            with self.subTest(path=path), self.assertRaises(rehearsal.Failure):
                rehearsal.read_private_json(path)

    def test_relative_and_noncanonical_inputs_are_refused(self):
        (self.root / 'child').mkdir()
        paths = (Path('credentials.json'),
                 self.root / 'child' / '..' / self.path.name)
        for path in paths:
            with self.subTest(path=path), self.assertRaises(rehearsal.Failure):
                rehearsal.read_private_json(path)

    def test_repository_hosted_secrets_are_refused(self):
        (self.root / '.git').mkdir()
        (self.root / '.git' / 'HEAD').write_text('ref: refs/heads/main\n')
        with self.assertRaises(rehearsal.Failure):
            rehearsal.read_private_json(self.path)
        self.assertIn('PRIVATE-CANARY', self.path.read_text())

    def test_worktree_gitfile_also_marks_repository(self):
        (self.root / '.git').write_text('gitdir: /unrelated/worktrees/test\n')
        with self.assertRaises(rehearsal.Failure):
            rehearsal.read_private_json(self.path)

    def test_known_checkout_refused_when_git_metadata_is_hidden(self):
        self.assertFalse((self.root / '.git').exists())
        with patch.object(rehearsal, 'ROOT', self.root):
            with self.assertRaisesRegex(rehearsal.Failure, '^repository_secret_refused$'):
                rehearsal.read_private_json(self.path)
        self.assertIn('PRIVATE-CANARY', self.path.read_text())


class StageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.checkout = self.root / 'checkout'
        self.checkout.mkdir()

    def test_stage_at_or_below_known_checkout_is_refused_without_git_metadata(self):
        self.assertFalse((self.checkout / '.git').exists())
        with patch.object(rehearsal, 'ROOT', self.checkout):
            for stage in (self.checkout, self.checkout / 'artifacts' / 'run'):
                with self.subTest(stage=stage), self.assertRaisesRegex(
                        rehearsal.Failure, '^repository_stage_refused$'):
                    rehearsal.validate_stage_path(stage)
            # A sibling with the same name prefix is outside the checkout.
            rehearsal.validate_stage_path(self.root / 'checkout-artifacts' / 'run')

    def test_refused_stage_never_runs_docker_or_writes_diagnostics_in_checkout(self):
        stage = self.checkout / 'run'
        (stage / 'private').mkdir(parents=True)
        output = io.StringIO()
        with patch.object(rehearsal, 'ROOT', self.checkout), patch.object(
                rehearsal, 'Rehearsal') as constructor, patch.object(
                rehearsal.media, 'write_private') as write, redirect_stdout(output):
            code = rehearsal.main(['cleanup', '--stage', str(stage)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['error'], 'repository_stage_refused')
        constructor.assert_not_called()
        write.assert_not_called()
        self.assertEqual(list((stage / 'private').iterdir()), [])


class StorageBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.spec = dict(bucket='vidra-acceptance-v078-20261017-fixture',
                         bucket_id='0123456789abcdef01234567',
                         endpoint='s3.us-west-004.backblazeb2.com',
                         region='us-west-004')
        self.credentials = dict(access_key='PRIVATE-KEY', secret_key='PRIVATE-SECRET')

    def test_accepts_only_dedicated_release_bucket_and_credentials(self):
        rehearsal.validate_storage(self.spec, self.credentials)

    def test_rejects_shared_bucket_wrong_release_and_endpoint_injection(self):
        changes = ({'bucket': 'shared-production'},
                   {'bucket': 'vidra-acceptance-v077-20261017-fixture'},
                   {'endpoint': 'https://s3.us-west-004.backblazeb2.com'},
                   {'endpoint': 's3.us-west-004.backblazeb2.com/escape'},
                   {'endpoint': 's3.us-west-004.backblazeb2.com.evil.invalid'},
                   {'endpoint': 's3.us-east-005.backblazeb2.com'},
                   {'bucket_id': 'not-a-bucket-id'},
                   {'region': 'us-west-004\n'})
        for change in changes:
            spec = {**self.spec, **change}
            with self.subTest(change=change), self.assertRaises(rehearsal.Failure):
                rehearsal.validate_storage(spec, self.credentials)

    def test_extra_spec_or_credential_fields_are_refused(self):
        for spec, credentials in (({**self.spec, 'secret_key': 'PRIVATE-SECRET'}, self.credentials),
                                  (self.spec, {**self.credentials, 'account_id': 'unused'}),
                                  (self.spec, {**self.credentials, 'secret_key': ''}),
                                  (self.spec, {'access_key': 'PRIVATE-KEY'})):
            with self.subTest(spec_keys=tuple(spec), credential_keys=tuple(credentials)), \
                    self.assertRaises(rehearsal.Failure):
                rehearsal.validate_storage(spec, credentials)


class FrozenImageTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((ROOT / 'releases/v0.7.8.json').read_text())

    def test_uses_amd64_image_digest_from_frozen_record(self):
        actual = rehearsal.image_refs(self.record)
        expected = {role: component['image']['repository'] + '@' +
                    component['image']['platforms']['linux/amd64']
                    for role, component in self.record['components'].items()}
        self.assertEqual(actual, expected)
        for role in expected:
            self.assertNotIn(self.record['components'][role]['image']['index_digest'],
                             actual[role])

    def test_wrong_release_core_commit_and_mutable_image_are_refused(self):
        mutations = (
            lambda record: record.update(release='v0.7.7'),
            lambda record: record['components']['core'].update(commit='0' * 40),
            lambda record: record['components']['core']['image']['platforms'].update(
                {'linux/amd64': 'latest'}),
            lambda record: record['components']['user']['image']['platforms'].pop('linux/amd64'),
            lambda record: record['components']['search']['image']['platforms'].update(
                {'linux/amd64': 'sha256:bad'}),
        )
        for mutation in mutations:
            record = copy.deepcopy(self.record)
            mutation(record)
            with self.subTest(record=record['release']), self.assertRaises(rehearsal.Failure):
                rehearsal.image_refs(record)


class ComposeIsolationTests(unittest.TestCase):
    def setUp(self):
        record = json.loads((ROOT / 'releases/v0.7.8.json').read_text())
        self.images = rehearsal.image_refs(record)
        self.state = dict(images=self.images, api_port=18080, frontend_port=13000,
                          db_password='fixture-db', source_password='fixture-source',
                          reader_password='fixture-reader', jwt_secret='fixture-jwt',
                          kek='fixture-kek', search_secret='fixture-search')
        self.spec = dict(bucket='vidra-acceptance-v078-20261017-fixture',
                         endpoint='s3.us-west-004.backblazeb2.com', region='us-west-004')
        self.credentials = dict(access_key='fixture-key', secret_key='fixture-secret')

    def model(self):
        return rehearsal.compose_model(self.state, self.spec, self.credentials,
                                       Path('/private/fixture/source-media'), Path('/etc/fixture-ca.pem'))

    def test_candidate_services_keep_databases_private_and_external_side_effects_disabled(self):
        services = self.model()['services']
        for name in ('postgres', 'source', 'redis', 'search'):
            with self.subTest(service=name):
                self.assertFalse(services[name].get('ports'))
        self.assertEqual(services['api']['ports'], ['127.0.0.1:18080:8080'])
        self.assertEqual(services['frontend']['ports'], ['127.0.0.1:13000:3000'])
        for service, role in (('api', 'core'), ('frontend', 'user'), ('search', 'search')):
            with self.subTest(service=service):
                self.assertEqual(services[service]['image'], self.images[role])
                self.assertEqual(services[service]['platform'], 'linux/amd64')
        mounts = {entry['target']: entry for entry in services['api']['volumes']}
        self.assertEqual(set(mounts), {'/peertube-source', '/run/ca.pem'})
        self.assertEqual(mounts['/peertube-source']['source'], '/private/fixture/source-media')
        self.assertEqual(mounts['/run/ca.pem']['source'], '/etc/fixture-ca.pem')
        self.assertTrue(all(entry['type'] == 'bind' and entry['read_only'] is True
                            for entry in mounts.values()))
        env = services['api']['environment']
        for flag in ('REGISTRATION_ENABLED', 'FEDERATION_ENABLED', 'MAIL_ENABLED',
                     'DEV_MAIL_CAPTURE_ENABLED', 'IPFS_ENABLED', 'CHANNEL_SYNC_ENABLED',
                     'MEDIA_GC_ENABLED', 'FEATURE_LIVE_ENABLED'):
            with self.subTest(flag=flag):
                self.assertEqual(env[flag], 'false')
        self.assertEqual(env['STORAGE_BACKEND'], 's3')
        self.assertEqual(env['STORAGE_S3_ENDPOINT'], self.spec['endpoint'])
        self.assertEqual(env['STORAGE_S3_USE_SSL'], 'true')
        self.assertEqual(env['SSL_CERT_FILE'], '/run/ca.pem')
        self.assertEqual(env['PEERTUBE_SOURCE_STORAGE_LOCAL_ROOT'], '/peertube-source')
        self.assertEqual(env['PEERTUBE_IMPORT_MEDIA_MODE'], 'copy')
        self.assertEqual(env['SEARCH_SERVICE_URL'], 'http://search:8080')

    def test_outer_proxy_hostname_does_not_replace_docker_container_proxy_defaults(self):
        outer = dict(HTTP_PROXY='http://proxy:8080', HTTPS_PROXY='http://proxy:8080',
                     http_proxy='http://proxy:8080', https_proxy='http://proxy:8080',
                     NO_PROXY='existing.internal', no_proxy='existing-lower.internal')
        with patch.dict(os.environ, outer):
            env = self.model()['services']['api']['environment']
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            with self.subTest(key=key):
                self.assertNotIn(key, env)
        for key, original in (('NO_PROXY', 'existing.internal'),
                              ('no_proxy', 'existing-lower.internal')):
            with self.subTest(key=key):
                self.assertTrue({original, '127.0.0.1', 'localhost', 'postgres', 'source',
                                 'redis', 'api', 'frontend', 'search'} <= set(env[key].split(',')))


def mapped_rows():
    return [dict(source_id=media.UUIDS[case],
                 vidra_id=f'10000000-0000-4000-8000-{index:012d}',
                 status='done', title='Synthetic ' + case,
                 privacy={'unlisted': 'unlisted', 'private': 'private',
                          'internal': 'internal', 'password': 'private'}.get(case, 'public'),
                 state='draft' if case == 'draft' else 'published',
                 blocked=case == 'blacklisted')
            for index, case in enumerate(media.CASES, 1)]


class MappingEvidenceTests(unittest.TestCase):
    def test_all_ten_metadata_rows_include_missing_media_and_blocked_public_video(self):
        rehearsal.verify_mapping(mapped_rows())

    def test_missing_duplicate_and_unknown_source_rows_are_refused(self):
        rows = mapped_rows()
        candidates = (rows[:-1], [*rows, rows[0]],
                      [{**rows[0], 'source_id': 'unknown'}, *rows[1:]])
        for candidate in candidates:
            with self.subTest(count=len(candidate)), self.assertRaises(rehearsal.Failure):
                rehearsal.verify_mapping(candidate)

    def test_incomplete_ledger_and_shared_target_identity_are_refused(self):
        for change in ({'status': 'failed'}, {'status': 'pending'}, {'vidra_id': None},
                       {'vidra_id': mapped_rows()[1]['vidra_id']}):
            rows = mapped_rows()
            rows[0].update(change)
            with self.subTest(change=change), self.assertRaises(rehearsal.Failure):
                rehearsal.verify_mapping(rows)

    def test_privacy_draft_and_blacklist_evidence_must_match_source_semantics(self):
        changes = (('password', {'privacy': 'public'}),
                   ('internal', {'privacy': 'private'}),
                   ('draft', {'state': 'published'}),
                   ('blacklisted', {'blocked': False}),
                   ('public', {'blocked': True}),
                   ('public', {'title': 'Wrong target'}))
        for case, change in changes:
            rows = mapped_rows()
            rows[media.CASES.index(case)].update(change)
            with self.subTest(case=case, change=change), self.assertRaises(rehearsal.Failure):
                rehearsal.verify_mapping(rows)


class AssetReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.inventory = {'videos': {}, 'files': {}}
        self.originals, self.masters, self.captions, self.artwork = [], [], [], []
        for row, case in zip(mapped_rows(), media.CASES):
            entry = self.inventory['videos'][case] = dict(uuid=row['source_id'], original=None, hls=None)
            if case not in ('hls_only', 'split_audio', 'missing_media'):
                entry['original'] = f'web-videos/{row["source_id"]}.mp4'
                self.put(entry['original'], b'synthetic original ' + case.encode())
                self.originals.append(dict(source_id=row['source_id'],
                                           storage_key=f'web-videos/{row["vidra_id"]}.mp4',
                                           original_name=Path(entry['original']).name))
            if case in ('public', 'hls_only', 'split_audio'):
                prefix = f'streaming-playlists/hls/{row["source_id"]}/'
                entry['hls'] = prefix + 'master.m3u8'
                self.put(entry['hls'], b'#EXTM3U\nvideo.m3u8\n')
                for track in (('video', 'audio') if case == 'split_audio' else ('video',)):
                    self.put(prefix + track + '.m3u8',
                             f'#EXTM3U\n#EXT-X-MAP:URI="{track}-init.mp4"\n'
                             f'#EXTINF:4,\n{track}-000.m4s\n#EXT-X-ENDLIST\n'.encode())
                    self.put(prefix + track + '-init.mp4', b'synthetic init ' + track.encode())
                    self.put(prefix + track + '-000.m4s', b'synthetic segment ' + track.encode())
                self.masters.append(dict(source_id=row['source_id'],
                                         master_key=entry['hls']))
        public = mapped_rows()[0]
        self.put('captions/fixture-en.vtt', b'WEBVTT\n\n00:00.000 --> 00:04.000\nfixture\n')
        self.captions.append(dict(source_id=public['source_id'], language='en',
                                  storage_key=f'captions/{public["vidra_id"]}/import-1.vtt'))
        for kind, original, destination in (
                ('thumbnail', 'thumbnails/poster.jpg', 'thumbnails'),
                ('storyboard', 'storyboards/sprite.jpg', 'storyboards')):
            self.put(original, b'synthetic artwork ' + kind.encode())
            self.artwork.append(dict(source_id=public['source_id'], kind=kind,
                                     original_name=Path(original).name,
                                     storage_key=f'{destination}/{public["vidra_id"]}.jpg'))

    def put(self, relative, data):
        path = self.root / 'source-media' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.inventory['files']['source-media/' + relative] = {
            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

    def pairs(self):
        return rehearsal.asset_pairs(self.inventory, self.originals, self.masters,
                                     self.captions, self.artwork, self.root)

    def test_every_copied_file_has_its_source_size_and_hash(self):
        pairs = self.pairs()
        self.assertEqual(len(pairs), len(self.inventory['files']))
        self.assertEqual(len({pair['key'] for pair in pairs}), len(pairs))
        for pair in pairs:
            with self.subTest(key=pair['key']):
                source = self.inventory['files'][pair['source_relative']]
                self.assertEqual(pair['bytes'], source['size'])
                self.assertEqual(pair['sha256'], source['sha256'])
        split = next(row for row in self.masters if row['source_id'] == media.UUIDS['split_audio'])
        destination = str(Path(split['master_key']).parent)
        self.assertIn(destination + '/audio-000.m4s', {pair['key'] for pair in pairs})
        self.assertIn(destination + '/audio-init.mp4', {pair['key'] for pair in pairs})

    def test_omitted_original_or_hls_tree_is_refused(self):
        for collection in (self.originals, self.masters, self.captions, self.artwork):
            saved = list(collection)
            collection.pop()
            with self.subTest(kind=saved[0].keys()), self.assertRaises(rehearsal.Failure):
                self.pairs()
            collection[:] = saved

    def test_shared_destination_key_is_refused(self):
        self.originals[1]['storage_key'] = self.originals[0]['storage_key']
        with self.assertRaises(rehearsal.Failure):
            self.pairs()

    def test_unknown_source_identity_is_refused(self):
        self.originals[0]['source_id'] = 'unknown-source'
        with self.assertRaises(rehearsal.Failure):
            self.pairs()

    def test_source_file_tampering_is_refused(self):
        original = self.inventory['videos']['public']['original']
        path = self.root / 'source-media' / original
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        with self.assertRaises(rehearsal.Failure):
            self.pairs()

    def test_recorded_original_hash_must_match_source_bytes(self):
        self.originals[0]['sha256'] = '0' * 64
        with self.assertRaises(rehearsal.Failure):
            self.pairs()

    def test_hls_copy_preserves_source_uuid_tree(self):
        self.masters[0]['master_key'] = (
            f'streaming-playlists/hls/{mapped_rows()[0]["vidra_id"]}/master.m3u8')
        with self.assertRaises(rehearsal.Failure):
            self.pairs()

    def test_source_symlink_is_refused(self):
        original = self.root / 'source-media' / self.inventory['videos']['public']['original']
        outside = self.root / 'outside'
        outside.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(outside)
        with self.assertRaises(rehearsal.Failure):
            self.pairs()

    def test_relative_destination_cannot_escape_storage_root(self):
        for key in ('../escape.mp4', '/absolute.mp4', 'web-videos/../escape.mp4',
                    'https://other.invalid/private.mp4', ''):
            self.originals[0]['storage_key'] = key
            with self.subTest(key=key), self.assertRaises(rehearsal.Failure):
                self.pairs()

    def test_inventory_source_cannot_escape_media_root(self):
        original = self.inventory['videos']['public']['original']
        data = (self.root / 'source-media' / original).read_bytes()
        (self.root / 'outside.mp4').write_bytes(data)
        self.inventory['videos']['public']['original'] = '../outside.mp4'
        self.originals[0]['original_name'] = 'outside.mp4'
        self.inventory['files']['source-media/../outside.mp4'] = {
            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        with self.assertRaises(rehearsal.Failure):
            self.pairs()


if __name__ == '__main__':
    unittest.main()
