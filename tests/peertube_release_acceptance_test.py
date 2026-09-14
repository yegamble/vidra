"""Guard archive handling, candidate derivation and the sole Compose adaptation of the COPY rehearsal."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import peertube_release_acceptance as p
from peertube_release_checks import original_files, match_assets
from peertube_release_export import collect_secrets, env_secrets, json_values, owner_password, reject_secrets

ROOT = Path(__file__).resolve().parents[1]
B2_SPEC = {'bucket': 'vidra-acceptance-v065-20260914-media', 'bucket_id': 'e565124b996984e8a7070215',
           'region': 'us-east-005', 'endpoint': 's3.us-east-005.backblazeb2.com'}


class PeerTubeReleaseTests(unittest.TestCase):
    def test_export_rejects_pem_content_but_not_scanner_literals(self):
        marker = '-----BEGIN ' + 'RSA PRIVATE KEY-----'
        reject_secrets(repr(marker), [])
        for text in (marker + '\nREDACTED', marker + r'\nREDACTED', 'prefix-test-secret-suffix', '$2b$12$' + 'A' * 53):
            with self.assertRaises(AssertionError):
                reject_secrets(text, ['test-secret'])

    def test_byte_equal_files_must_belong_to_correct_video(self):
        source = [{'source_id': 'one', 'filename': 'a'}, {'source_id': 'two', 'filename': 'b'}]
        match_assets(source, source, 'filename')
        for wrong in ([source[0], source[0]],
                      [{'source_id': 'one', 'filename': 'b'}, {'source_id': 'two', 'filename': 'a'}]):
            with self.assertRaises(ValueError):
                match_assets(source, wrong, 'filename')

    def test_progressive_reconciliation_excludes_image_metadata(self):
        originals = [{'kind': 'original', 'storage_key': str(n)} for n in range(5)]
        images = [{'kind': kind} for kind in ('thumbnail', 'storyboard', 'storyboard_vtt') for _ in range(7)]
        self.assertEqual(original_files(originals + images), originals)
        with self.assertRaises(ValueError):
            original_files(originals[:4] + images)

    def archive(self, name, kind=tarfile.REGTYPE):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            archive.addfile(member)
        data.seek(0)
        return tarfile.open(fileobj=data)

    def test_only_regular_media_is_extracted_read_only(self):
        for name in ('source-config8/production.yaml', 'source-media8/logs/server.log', '._source-media8'):
            with self.archive(name) as archive:
                self.assertEqual(list(p.media_members(archive)), [])
        with self.archive('source-media8/web-videos/a.mp4') as archive:
            self.assertEqual(list(p.media_members(archive))[0].mode, 0o444)

    def test_traversal_and_links_are_refused(self):
        for name, kind in [('source-media8/../../outside', tarfile.REGTYPE),
                           ('source-media8/link', tarfile.SYMTYPE)]:
            with self.archive(name, kind) as archive:
                with self.assertRaises(ValueError):
                    list(p.media_members(archive))

    def test_mount_preserves_images_and_existing_volumes(self):
        original = ('volumes:\n  - media_data:/app/data\n  - transcode_tmp:/scratch\nimage: frozen\n'
                    'services:\n  prep-volumes:\n    volumes:\n      - media_data:/app/data\n')
        changed = p.source_mount(original, '/root/rehearsal/source-media8')
        self.assertEqual(changed.replace('  - /root/rehearsal/source-media8:/peertube-source:ro\n', ''), original)
        for bad in ('', original + original):
            with self.assertRaises(ValueError):
                p.source_mount(bad, '/root/rehearsal/source-media8')


class MigrationDrillCandidateTests(unittest.TestCase):
    """The drill must take its release from the baseline it is run against.

    Hard-coding v0.6.4 made the harness unrunnable on the v0.6.5 host, and —
    worse — a literal that still parses on a newer host would have named the
    wrong release in the evidence it produced.
    """

    def baseline(self, tmp, storage):
        (tmp / 'storage.json').write_text(json.dumps(storage) + '\n')
        return tmp

    def test_release_tag_comes_from_the_committed_candidate(self):
        candidate = json.loads((ROOT / 'docs/evidence/release-v0.6.5-verification/manifest.json').read_text())
        self.assertEqual(p.release_tag(candidate), 'v0.6.5')
        self.assertEqual(p.frozen_cli_sha256(candidate, 'v0.6.5'),
                         candidate['assets']['vidra_v0.6.5_linux_amd64']['sha256'])
        for bad in ({'tag': 'v0.6'}, {'tag': 'main'}, {'tag': 'v0.6.5-rc1'}, {'tag': None}, {}):
            with self.assertRaises(ValueError):
                p.release_tag(bad)

    def test_frozen_cli_asset_key_is_keyed_to_the_tag(self):
        candidate = {'assets': {'vidra_v0.6.5_linux_amd64': {'sha256': 'a' * 64}}}
        self.assertEqual(p.frozen_cli_sha256(candidate, 'v0.6.5'), 'a' * 64)
        # A baseline that ships no asset for this release must say so, not
        # compare the installed CLI against a KeyError or another release.
        with self.assertRaises(ValueError):
            p.frozen_cli_sha256(candidate, 'v0.6.4')

    def test_scope_prose_names_the_release_under_rehearsal(self):
        self.assertIn('packaged v0.6.5 admin import', p.scope('v0.6.5'))
        self.assertIn('packaged v0.6.4 admin import', p.scope('v0.6.4'))

    def test_source_container_is_named_for_release_and_day(self):
        self.assertEqual(p.source_container('v0.6.5', '20260914'), 'vidra-v065-migration-source-20260914')
        self.assertEqual(p.source_container('v0.6.4', '20260911'), 'vidra-v064-migration-source-20260911')
        self.assertRegex(p.source_container('v0.6.5'), r'^vidra-v065-migration-source-[0-9]{8}$')
        for bad in ('main', 'v0.6', 'v0.6.5-rc1'):
            with self.assertRaises(ValueError):
                p.source_container(bad)

    def test_bucket_comes_from_the_baseline_storage_record(self):
        with tempfile.TemporaryDirectory() as name:
            baseline = self.baseline(Path(name), {'backend': 'b2', 'spec': B2_SPEC})
            self.assertEqual(p.baseline_storage(baseline, 'v0.6.5'), B2_SPEC)
            # The recorded bucket must belong to the release being rehearsed.
            with self.assertRaises(ValueError) as caught:
                p.baseline_storage(baseline, 'v0.6.4')
            self.assertIn('v0.6.4 acceptance bucket', str(caught.exception))

    def test_local_storage_baseline_is_refused(self):
        with tempfile.TemporaryDirectory() as name:
            baseline = self.baseline(Path(name), {'backend': 'local'})
            with self.assertRaises(ValueError) as caught:
                p.baseline_storage(baseline, 'v0.6.5')
            self.assertIn('B2', str(caught.exception))
            self.assertIn('local', str(caught.exception))


class ExportSecretSourceTests(unittest.TestCase):
    """Every named secret source must exist and yield a value.

    The scrub is the only thing standing between the private stage and a
    published archive: a missing key file must refuse the export, never quietly
    scan for one credential fewer.
    """

    def test_missing_or_empty_secret_source_refuses_the_export(self):
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            env = tmp / 'source.env'
            env.write_text('# comment\nPOSTGRES_PASSWORD=generated-secret-value\nPOSTGRES_DB=peertube\n')
            owner = tmp / 'owner.json'
            owner.write_text(json.dumps({'password': 'owner-secret-value'}))
            key = tmp / 'b2-key.json'
            key.write_text(json.dumps({'access_key': 'access-value-x', 'secret_key': 'secret-value-x'}))
            self.assertEqual(collect_secrets([(env, env_secrets), (owner, owner_password), (key, json_values)]),
                             ['generated-secret-value', 'owner-secret-value', 'access-value-x', 'secret-value-x'])
            for path in (tmp / 'absent.env', tmp / 'private' / 'source.env'):
                with self.assertRaises(AssertionError):
                    collect_secrets([(path, env_secrets)])
            empty = tmp / 'empty.env'
            empty.write_text('# no credentials here\nPOSTGRES_DB=peertube\n')
            with self.assertRaises(AssertionError):
                collect_secrets([(empty, env_secrets)])
